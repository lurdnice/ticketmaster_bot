from typing import List, Dict
from datetime import datetime

class EmailTemplates:
    @staticmethod
    def get_event_email_template(events: List[Dict], search_query: str, user_email: str) -> str:
        """Generate beautiful HTML email template"""
        
        events_html = ""
        for idx, event in enumerate(events, 1):
            seat_info = ""
            if event.get('seat_categories'):
                seat_info = "<h4>🎟️ Available Seating Sections:</h4><ul>"
                for seat in event['seat_categories'][:3]:
                    seat_info += f"<li>{seat}</li>"
                seat_info += "</ul>"
            
            # Event image
            image_html = ""
            if event.get('image'):
                image_html = f'<img src="{event["image"]}" alt="{event["title"]}" style="width:100%; max-width:400px; border-radius:10px; margin:15px 0;">'
            
            events_html += f"""
            <div style="border:2px solid #e0e0e0; border-radius:15px; padding:20px; margin-bottom:30px; background-color:#ffffff;">
                <h2 style="color:#0066cc; margin-top:0;">🎵 {idx}. {event.get('title', 'Event')}</h2>
                {image_html}
                <table style="width:100%; border-collapse:collapse;">
                    <tr>
                        <td style="padding:8px 0;"><strong>📅 Date & Time:</strong></td>
                        <td style="padding:8px 0;">{event.get('date', 'Not specified')}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;"><strong>📍 Venue:</strong></td>
                        <td style="padding:8px 0;">{event.get('venue', 'Not specified')}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 0;"><strong>💰 Price Range:</strong></td>
                        <td style="padding:8px 0;"><span style="background-color:#4CAF50; color:white; padding:3px 8px; border-radius:5px;">{event.get('price', 'Check website')}</span></td>
                    </tr>
                </table>
                {seat_info}
                <div style="margin-top:15px;">
                    <a href="{event.get('url', '#')}" style="display:inline-block; background-color:#0066cc; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">🎫 Get Tickets Now</a>
                </div>
                <hr style="margin:15px 0;">
                <p style="color:#666; font-size:12px; margin:0;">Event ID: {event.get('id', idx)}</p>
            </div>
            """
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Ticketmaster Norway - {search_query}</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background-color: #f4f4f4;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 20px auto;
                    background-color: #ffffff;
                    border-radius: 15px;
                    overflow: hidden;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 28px;
                }}
                .content {{
                    padding: 30px;
                }}
                .footer {{
                    background-color: #f8f9fa;
                    padding: 20px;
                    text-align: center;
                    font-size: 12px;
                    color: #666;
                }}
                .alert {{
                    background-color: #fff3cd;
                    border-left: 4px solid #ffc107;
                    padding: 15px;
                    margin: 20px 0;
                    border-radius: 5px;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background-color: #28a745;
                    color: white;
                    text-decoration: none;
                    border-radius: 5px;
                    margin-top: 15px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎫 Ticketmaster Norway</h1>
                    <p>Your Personal Event Discovery Assistant</p>
                </div>
                
                <div class="content">
                    <h2>🎯 Search Results for: "{search_query}"</h2>
                    <p>Hello <strong>{user_email}</strong>,</p>
                    <p>We found <strong>{len(events)} exciting events</strong> matching your search!</p>
                    
                    <div class="alert">
                        <strong>⚠️ Quick Tips:</strong><br>
                        • Tickets sell fast - act quickly!<br>
                        • Prices shown are subject to change<br>
                        • Click "Get Tickets Now" for immediate purchase
                    </div>
                    
                    {events_html}
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="https://ticketmaster.no" class="button">🔍 Browse More Events</a>
                    </div>
                    
                    <p style="font-size: 14px; color: #666;">
                        <strong>Need help?</strong> Reply to this email or contact our support team.<br>
                        <strong>Pro tip:</strong> Save this email for quick access to event links!
                    </p>
                </div>
                
                <div class="footer">
                    <p>&copy; 2024 Ticketmaster Norway Bot | Powered by Resend</p>
                    <p>You received this email because you requested event information via Telegram.</p>
                    <p><small>Ticketmaster is a registered trademark. This is an independent bot service.</small></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_content
    
    @staticmethod
    def get_confirmation_email(email: str) -> str:
        """Email confirmation template"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background-color: #f4f4f4;
                    padding: 20px;
                }}
                .container {{
                    max-width: 500px;
                    margin: 0 auto;
                    background-color: white;
                    padding: 30px;
                    border-radius: 10px;
                    text-align: center;
                }}
                .success {{
                    color: #28a745;
                    font-size: 48px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="success">✅</div>
                <h2>Email Confirmed!</h2>
                <p>Your email <strong>{email}</strong> has been successfully registered.</p>
                <p>You will now receive event updates and search results to this email.</p>
                <p><small>You can change this anytime by sending /email to the bot.</small></p>
            </div>
        </body>
        </html>
        """